package collector

import "time"

// Metric is the canonical data unit emitted by every collector.
// Tags carry optional dimensional context (e.g. device="sda", mount="/").
type Metric struct {
	ServerID  string            `json:"server_id"`
	Name      string            `json:"metric_name"`
	Value     float64           `json:"value"`
	Timestamp time.Time         `json:"timestamp"`
	Tags      map[string]string `json:"tags,omitempty"`
}
