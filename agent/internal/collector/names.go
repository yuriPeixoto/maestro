package collector

import (
	"fmt"
	"regexp"
)

// Metric name constants. All names follow Prometheus snake_case conventions:
//   - snake_case only (no camelCase, kebab-case, or dots)
//   - unit suffix where applicable (_bytes, _percent, _seconds, _per_sec)
//   - pattern: ^[a-z][a-z0-9_]*[a-z0-9]$
//
// Add new metric names here — never use string literals in collector files.
const (
	// CPU
	MetricCPUUsagePercent = "cpu_usage_percent"

	// Memory
	MetricMemoryUsedBytes      = "memory_used_bytes"
	MetricMemoryAvailableBytes = "memory_available_bytes"
	MetricMemoryUsagePercent   = "memory_usage_percent"

	// Disk I/O
	MetricDiskReadBytesPerSec  = "disk_read_bytes_per_sec"
	MetricDiskWriteBytesPerSec = "disk_write_bytes_per_sec"

	// Disk Space
	MetricDiskUsedBytes    = "disk_used_bytes"
	MetricDiskTotalBytes   = "disk_total_bytes"
	MetricDiskUsagePercent = "disk_usage_percent"

	// Network
	MetricNetworkBytesInPerSec  = "network_bytes_in_per_sec"
	MetricNetworkBytesOutPerSec = "network_bytes_out_per_sec"

	// Process
	MetricProcessCount = "process_count"
)

// validName matches Prometheus-style metric names:
// starts with a lowercase letter, contains only lowercase letters, digits, and underscores,
// ends with a lowercase letter or digit.
var validName = regexp.MustCompile(`^[a-z][a-z0-9_]*[a-z0-9]$`)

// ValidateName returns an error if name does not conform to the Prometheus
// snake_case naming convention enforced by this package.
func ValidateName(name string) error {
	if !validName.MatchString(name) {
		return fmt.Errorf("invalid metric name %q: must match ^[a-z][a-z0-9_]*[a-z0-9]$", name)
	}
	return nil
}
