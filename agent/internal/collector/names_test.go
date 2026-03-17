package collector_test

import (
	"testing"

	"github.com/yuriPeixoto/maestro/agent/internal/collector"
)

func TestValidateName_ValidNames(t *testing.T) {
	valid := []string{
		collector.MetricCPUUsagePercent,
		collector.MetricMemoryUsedBytes,
		collector.MetricMemoryAvailableBytes,
		collector.MetricMemoryUsagePercent,
		collector.MetricDiskReadBytesPerSec,
		collector.MetricDiskWriteBytesPerSec,
		collector.MetricDiskUsedBytes,
		collector.MetricDiskTotalBytes,
		collector.MetricDiskUsagePercent,
		collector.MetricNetworkBytesInPerSec,
		collector.MetricNetworkBytesOutPerSec,
		collector.MetricProcessCount,
		// generic valid patterns
		"ab",
		"a1",
		"a_b",
		"cpu_seconds_total",
		"http_requests_total",
	}
	for _, name := range valid {
		if err := collector.ValidateName(name); err != nil {
			t.Errorf("expected %q to be valid, got: %v", name, err)
		}
	}
}

func TestValidateName_InvalidNames(t *testing.T) {
	invalid := []string{
		"",               // empty
		"_starts_under",  // starts with underscore
		"1starts_digit",  // starts with digit
		"CamelCase",      // uppercase
		"kebab-case",     // hyphen
		"dot.separated",  // dot
		"trailing_",      // ends with underscore
		"CPU",            // all uppercase
		"a",              // single char (too short for pattern)
		"has space",      // space
		"metric__double", // double underscore (valid pattern-wise but semantically bad? actually valid)
	}

	// Note: double underscore IS technically valid per the regex — it matches [a-z0-9_]*.
	// Only the clearly bad patterns should fail.
	definitelyInvalid := []string{
		"",
		"_starts_under",
		"1starts_digit",
		"CamelCase",
		"kebab-case",
		"dot.separated",
		"trailing_",
		"CPU",
		"a",
		"has space",
	}
	_ = invalid // listed for documentation; only the subset below is asserted

	for _, name := range definitelyInvalid {
		if err := collector.ValidateName(name); err == nil {
			t.Errorf("expected %q to be invalid, but ValidateName returned nil", name)
		}
	}
}

func TestValidateName_AllDefinedConstantsAreValid(t *testing.T) {
	// Ensures that if a constant is ever accidentally changed to an invalid value,
	// this test catches it at compile+test time.
	constants := []string{
		collector.MetricCPUUsagePercent,
		collector.MetricMemoryUsedBytes,
		collector.MetricMemoryAvailableBytes,
		collector.MetricMemoryUsagePercent,
		collector.MetricDiskReadBytesPerSec,
		collector.MetricDiskWriteBytesPerSec,
		collector.MetricDiskUsedBytes,
		collector.MetricDiskTotalBytes,
		collector.MetricDiskUsagePercent,
		collector.MetricNetworkBytesInPerSec,
		collector.MetricNetworkBytesOutPerSec,
		collector.MetricProcessCount,
	}
	for _, c := range constants {
		if err := collector.ValidateName(c); err != nil {
			t.Errorf("constant %q failed validation: %v", c, err)
		}
	}
}