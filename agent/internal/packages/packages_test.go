package packages

import (
	"reflect"
	"strings"
	"testing"
)

func TestParseDpkg(t *testing.T) {
	out := strings.Join([]string{
		"apache2\t2.4.65-1~deb12u1\tii ",
		"apache2\t2.4.65-1~deb12u1\tii ", // apache2-bin: same source, collapses
		"openssh\t1:9.2p1-2+deb12u7\tii ",
		"nginx\t1.22.1-9\trc ", // removed, config files left behind
		"broken line",
		"\t\tii ",
		"",
	}, "\n")

	got := parseDpkg([]byte(out))
	want := []Package{
		{Name: "apache2", Version: "2.4.65-1~deb12u1"},
		{Name: "openssh", Version: "1:9.2p1-2+deb12u7"},
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("parseDpkg() = %+v, want %+v", got, want)
	}
}

func TestParseEcosystem(t *testing.T) {
	cases := []struct {
		name      string
		osRelease string
		want      string
	}{
		{"debian 12", "PRETTY_NAME=\"Debian GNU/Linux 12 (bookworm)\"\nVERSION_ID=\"12\"\nID=debian\n", "Debian:12"},
		{"debian testing has no version", "ID=debian\n", ""},
		{"ubuntu is not supported", "ID=ubuntu\nVERSION_ID=\"24.04\"\n", ""},
		{"empty", "", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := parseEcosystem(strings.NewReader(tc.osRelease)); got != tc.want {
				t.Fatalf("parseEcosystem() = %q, want %q", got, tc.want)
			}
		})
	}
}
