package watchdog

import (
	"errors"
	"fmt"
	"strconv"
	"strings"
	"time"
)

// Settings is what the watchdog binary reads from its environment.
type Settings struct {
	Config
	Interval      time.Duration
	Timeout       time.Duration
	TelegramToken string
	TelegramChat  string
	Announce      bool
}

const (
	defaultInterval = time.Minute
	defaultTimeout  = 10 * time.Second
	defaultFailures = 3
	defaultRemind   = time.Hour
)

// LoadSettings reads WATCHDOG_* and TELEGRAM_* variables through getenv.
//
//	WATCHDOG_TARGETS   name=url pairs separated by commas (required)
//	TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (required)
//	WATCHDOG_INTERVAL  between polls, Go duration (default 1m)
//	WATCHDOG_TIMEOUT   per request (default 10s)
//	WATCHDOG_FAILURES  consecutive failures before alerting (default 3)
//	WATCHDOG_REMIND    repeat while down, 0 to never repeat (default 1h)
//	WATCHDOG_LANGUAGE  pt-BR or en (default pt-BR)
//	WATCHDOG_ANNOUNCE  send a message on start (default true)
func LoadSettings(getenv func(string) string) (Settings, error) {
	targets, err := parseTargets(getenv("WATCHDOG_TARGETS"))
	if err != nil {
		return Settings{}, err
	}
	s := Settings{
		TelegramToken: strings.TrimSpace(getenv("TELEGRAM_BOT_TOKEN")),
		TelegramChat:  strings.TrimSpace(getenv("TELEGRAM_CHAT_ID")),
	}
	s.Targets = targets
	s.Texts = TextsFor(getenv("WATCHDOG_LANGUAGE"))
	if s.TelegramToken == "" || s.TelegramChat == "" {
		return Settings{}, errors.New("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
	}

	if s.Interval, err = durationOr(getenv("WATCHDOG_INTERVAL"), defaultInterval); err != nil {
		return Settings{}, fmt.Errorf("WATCHDOG_INTERVAL: %w", err)
	}
	if s.Timeout, err = durationOr(getenv("WATCHDOG_TIMEOUT"), defaultTimeout); err != nil {
		return Settings{}, fmt.Errorf("WATCHDOG_TIMEOUT: %w", err)
	}
	if s.RemindEvery, err = durationOr(getenv("WATCHDOG_REMIND"), defaultRemind); err != nil {
		return Settings{}, fmt.Errorf("WATCHDOG_REMIND: %w", err)
	}
	if s.FailuresBeforeAlert, err = intOr(getenv("WATCHDOG_FAILURES"), defaultFailures); err != nil || s.FailuresBeforeAlert < 1 {
		return Settings{}, errors.New("WATCHDOG_FAILURES must be a whole number of at least 1")
	}
	s.Announce = getenv("WATCHDOG_ANNOUNCE") != "false"
	return s, nil
}

func parseTargets(raw string) ([]Target, error) {
	var targets []Target
	seen := map[string]bool{}
	for pair := range strings.SplitSeq(raw, ",") {
		pair = strings.TrimSpace(pair)
		if pair == "" {
			continue
		}
		name, url, found := strings.Cut(pair, "=")
		name, url = strings.TrimSpace(name), strings.TrimSpace(url)
		if !found || name == "" || !(strings.HasPrefix(url, "http://") || strings.HasPrefix(url, "https://")) {
			return nil, fmt.Errorf("WATCHDOG_TARGETS: %q is not name=http(s)://url", pair)
		}
		if seen[name] {
			return nil, fmt.Errorf("WATCHDOG_TARGETS: %q appears twice", name)
		}
		seen[name] = true
		targets = append(targets, Target{Name: name, URL: url})
	}
	if len(targets) == 0 {
		return nil, errors.New("WATCHDOG_TARGETS is empty")
	}
	return targets, nil
}

func durationOr(raw string, fallback time.Duration) (time.Duration, error) {
	if strings.TrimSpace(raw) == "" {
		return fallback, nil
	}
	return time.ParseDuration(strings.TrimSpace(raw))
}

func intOr(raw string, fallback int) (int, error) {
	if strings.TrimSpace(raw) == "" {
		return fallback, nil
	}
	return strconv.Atoi(strings.TrimSpace(raw))
}
