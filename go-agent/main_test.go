package main

import (
	"encoding/json"
	"os"
	"testing"
	"time"
)

func TestEnvelopeMatchesV1Shape(t *testing.T) {
	cfg := config{NodeID: "go-test-01", DisplayName: "Go Test"}
	value := newEnvelope(cfg, "resources", 7, map[string]any{"cpu_percent": 1.5})
	body, err := payload(value)
	if err != nil {
		t.Fatal(err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(body, &decoded); err != nil {
		t.Fatal(err)
	}
	if decoded["schema_version"] != "1.0" {
		t.Fatalf("unexpected schema: %v", decoded["schema_version"])
	}
	if decoded["message_type"] != "resources" {
		t.Fatalf("unexpected message type: %v", decoded["message_type"])
	}
	nodeValue := decoded["node"].(map[string]any)
	if nodeValue["id"] != "go-test-01" {
		t.Fatalf("unexpected node id: %v", nodeValue["id"])
	}
}

func TestLoadConfigRejectsInvalidNodeID(t *testing.T) {
	t.Setenv("VPS_ID", "INVALID")
	t.Setenv("PUBLISH_INTERVAL", "15")
	if _, err := loadConfig(false); err == nil {
		t.Fatal("expected invalid node ID to fail")
	}
}

func TestCollectResourcesHasCoreMetrics(t *testing.T) {
	if _, err := os.Stat("/proc/stat"); err != nil {
		t.Skip("/proc is unavailable")
	}
	value, err := collectResources(time.Millisecond)
	if err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{
		"cpu_percent",
		"memory_percent",
		"disk_percent",
		"reporting",
	} {
		if _, ok := value[key]; !ok {
			t.Fatalf("missing core metric %s", key)
		}
	}
}
