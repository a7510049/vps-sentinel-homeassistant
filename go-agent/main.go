package main

import (
	"bufio"
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"

	mqtt "github.com/eclipse/paho.mqtt.golang"
)

const (
	schemaVersion = "1.0"
	topicRoot     = "vps-sentinel/v1/nodes"
	agentVersion  = "go-prototype"
)

var nodeIDPattern = regexp.MustCompile(`^[a-z0-9](?:[a-z0-9_-]{0,62}[a-z0-9])?$`)

type node struct {
	ID           string            `json:"id"`
	DisplayName  string            `json:"display_name"`
	AgentVersion string            `json:"agent_version"`
	Capabilities []string          `json:"capabilities"`
	Labels       map[string]string `json:"labels"`
}

type envelope struct {
	SchemaVersion string         `json:"schema_version"`
	MessageType   string         `json:"message_type"`
	Node          node           `json:"node"`
	ObservedAt    string         `json:"observed_at"`
	Sequence      uint64         `json:"sequence"`
	Data          map[string]any `json:"data"`
}

type config struct {
	NodeID      string
	DisplayName string
	Host        string
	Port        int
	Username    string
	Password    string
	TLS         bool
	CAFile      string
	Interval    time.Duration
}

func environment(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func loadConfig(requireBroker bool) (config, error) {
	hostname, _ := os.Hostname()
	nodeID := environment("VPS_ID", strings.ToLower(hostname))
	if !nodeIDPattern.MatchString(nodeID) {
		return config{}, errors.New("VPS_ID violates the v1 node contract")
	}
	port, err := strconv.Atoi(environment("MQTT_PORT", "1883"))
	if err != nil || port < 1 || port > 65535 {
		return config{}, errors.New("MQTT_PORT is invalid")
	}
	seconds, err := strconv.Atoi(environment("PUBLISH_INTERVAL", "15"))
	if err != nil || seconds < 10 {
		return config{}, errors.New("PUBLISH_INTERVAL must be at least 10")
	}
	result := config{
		NodeID:      nodeID,
		DisplayName: environment("VPS_NAME", hostname),
		Host:        os.Getenv("MQTT_HOST"),
		Port:        port,
		Username:    os.Getenv("MQTT_USERNAME"),
		Password:    os.Getenv("MQTT_PASSWORD"),
		TLS:         strings.EqualFold(os.Getenv("MQTT_TLS"), "true"),
		CAFile:      os.Getenv("MQTT_CA_FILE"),
		Interval:    time.Duration(seconds) * time.Second,
	}
	if requireBroker && result.Host == "" {
		return config{}, errors.New("MQTT_HOST is required")
	}
	return result, nil
}

func procValues(path string) (map[string]uint64, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	values := map[string]uint64{}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		fields := strings.Fields(strings.ReplaceAll(scanner.Text(), ":", " "))
		if len(fields) < 2 {
			continue
		}
		value, parseErr := strconv.ParseUint(fields[1], 10, 64)
		if parseErr == nil {
			values[fields[0]] = value
		}
	}
	return values, scanner.Err()
}

func cpuSample() ([2]uint64, error) {
	content, err := os.ReadFile("/proc/stat")
	if err != nil {
		return [2]uint64{}, err
	}
	line := strings.SplitN(string(content), "\n", 2)[0]
	fields := strings.Fields(line)
	if len(fields) < 5 || fields[0] != "cpu" {
		return [2]uint64{}, errors.New("/proc/stat has no aggregate CPU row")
	}
	var total uint64
	for _, field := range fields[1:] {
		value, parseErr := strconv.ParseUint(field, 10, 64)
		if parseErr != nil {
			return [2]uint64{}, parseErr
		}
		total += value
	}
	idle, _ := strconv.ParseUint(fields[4], 10, 64)
	if len(fields) > 5 {
		wait, _ := strconv.ParseUint(fields[5], 10, 64)
		idle += wait
	}
	return [2]uint64{total, idle}, nil
}

func round(value float64, places int) float64 {
	scale := 1.0
	for range places {
		scale *= 10
	}
	return float64(int64(value*scale+0.5)) / scale
}

func collectResources(delay time.Duration) (map[string]any, error) {
	before, err := cpuSample()
	if err != nil {
		return nil, err
	}
	time.Sleep(delay)
	after, err := cpuSample()
	if err != nil {
		return nil, err
	}
	totalDelta := after[0] - before[0]
	idleDelta := after[1] - before[1]
	cpu := 0.0
	if totalDelta > 0 {
		cpu = 100 * float64(totalDelta-idleDelta) / float64(totalDelta)
	}
	memory, err := procValues("/proc/meminfo")
	if err != nil {
		return nil, err
	}
	totalBytes := memory["MemTotal"] * 1024
	availableBytes := memory["MemAvailable"] * 1024
	usedBytes := totalBytes - availableBytes
	memoryPercent := 0.0
	if totalBytes > 0 {
		memoryPercent = 100 * float64(usedBytes) / float64(totalBytes)
	}
	var disk syscall.Statfs_t
	if err := syscall.Statfs("/", &disk); err != nil {
		return nil, err
	}
	diskTotal := disk.Blocks * uint64(disk.Bsize)
	diskFree := disk.Bavail * uint64(disk.Bsize)
	diskUsed := diskTotal - diskFree
	return map[string]any{
		"cpu_percent":         round(cpu, 1),
		"memory_percent":      round(memoryPercent, 1),
		"memory_used_gb":      round(float64(usedBytes)/1e9, 2),
		"memory_available_gb": round(float64(availableBytes)/1e9, 2),
		"memory_total_gb":     round(float64(totalBytes)/1e9, 2),
		"disk_percent":        round(100*float64(diskUsed)/float64(diskTotal), 1),
		"disk_used_gb":        round(float64(diskUsed)/1e9, 2),
		"disk_free_gb":        round(float64(diskFree)/1e9, 2),
		"disk_total_gb":       round(float64(diskTotal)/1e9, 2),
		"reporting":           true,
	}, nil
}

func newEnvelope(cfg config, kind string, sequence uint64, data map[string]any) envelope {
	return envelope{
		SchemaVersion: schemaVersion,
		MessageType:   kind,
		Node: node{
			ID:           cfg.NodeID,
			DisplayName:  cfg.DisplayName,
			AgentVersion: agentVersion,
			Capabilities: []string{"resources.core"},
			Labels:       map[string]string{},
		},
		ObservedAt: time.Now().UTC().Format(time.RFC3339Nano),
		Sequence:   sequence,
		Data:       data,
	}
}

func payload(value envelope) ([]byte, error) {
	return json.Marshal(value)
}

func topic(cfg config, kind string) string {
	return fmt.Sprintf("%s/%s/%s", topicRoot, cfg.NodeID, kind)
}

func tlsConfig(cfg config) (*tls.Config, error) {
	if !cfg.TLS {
		return nil, nil
	}
	roots, err := x509.SystemCertPool()
	if err != nil {
		return nil, err
	}
	if cfg.CAFile != "" {
		certificate, readErr := os.ReadFile(cfg.CAFile)
		if readErr != nil {
			return nil, readErr
		}
		if !roots.AppendCertsFromPEM(certificate) {
			return nil, errors.New("MQTT_CA_FILE contains no certificates")
		}
	}
	return &tls.Config{MinVersion: tls.VersionTLS12, RootCAs: roots}, nil
}

func publish(client mqtt.Client, cfg config, kind string, sequence uint64, data map[string]any, qos byte) error {
	body, err := payload(newEnvelope(cfg, kind, sequence, data))
	if err != nil {
		return err
	}
	token := client.Publish(topic(cfg, kind), qos, true, body)
	if !token.WaitTimeout(15 * time.Second) {
		return errors.New("MQTT publish timed out")
	}
	return token.Error()
}

func run(ctx context.Context, cfg config) error {
	scheme := "tcp"
	tlsSettings, err := tlsConfig(cfg)
	if err != nil {
		return err
	}
	if tlsSettings != nil {
		scheme = "ssl"
	}
	options := mqtt.NewClientOptions().
		AddBroker(fmt.Sprintf("%s://%s:%d", scheme, cfg.Host, cfg.Port)).
		SetClientID("vps-sentinel-go-" + cfg.NodeID).
		SetUsername(cfg.Username).
		SetPassword(cfg.Password).
		SetAutoReconnect(true).
		SetConnectRetry(true).
		SetMaxReconnectInterval(5 * time.Minute).
		SetTLSConfig(tlsSettings)

	offline, _ := payload(newEnvelope(cfg, "availability", 0, map[string]any{"status": "offline"}))
	options.SetWill(topic(cfg, "availability"), string(offline), 1, true)
	client := mqtt.NewClient(options)
	token := client.Connect()
	if !token.WaitTimeout(30*time.Second) || token.Error() != nil {
		if token.Error() != nil {
			return token.Error()
		}
		return errors.New("MQTT connection timed out")
	}
	defer client.Disconnect(1000)

	var sequence uint64 = 1
	if err := publish(client, cfg, "availability", sequence, map[string]any{"status": "online"}, 1); err != nil {
		return err
	}
	sequence++
	if err := publish(client, cfg, "metadata", sequence, map[string]any{
		"architecture": runtime.GOARCH,
		"os_name":      runtime.GOOS,
	}, 1); err != nil {
		return err
	}

	ticker := time.NewTicker(cfg.Interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			sequence++
			_ = publish(client, cfg, "availability", sequence, map[string]any{"status": "offline"}, 1)
			return nil
		case <-ticker.C:
			resources, collectErr := collectResources(100 * time.Millisecond)
			if collectErr != nil {
				return collectErr
			}
			sequence++
			if err := publish(client, cfg, "resources", sequence, resources, 0); err != nil {
				return err
			}
		}
	}
}

func main() {
	once := flag.Bool("once", false, "collect one v1 resources envelope and exit")
	flag.Parse()
	cfg, err := loadConfig(!*once)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	if *once {
		resources, collectErr := collectResources(100 * time.Millisecond)
		if collectErr != nil {
			fmt.Fprintln(os.Stderr, collectErr)
			os.Exit(1)
		}
		_ = json.NewEncoder(os.Stdout).Encode(newEnvelope(cfg, "resources", 1, resources))
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	if err := run(ctx, cfg); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}
