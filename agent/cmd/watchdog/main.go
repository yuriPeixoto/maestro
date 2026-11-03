// Command watchdog polls health endpoints from another host and reports on
// Telegram when one stops answering. See docs/watchdog.md.
package main

import (
	"context"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/yuriPeixoto/maestro/agent/internal/watchdog"
)

func main() {
	settings, err := watchdog.LoadSettings(os.Getenv)
	if err != nil {
		log.Fatalf("error: %v", err)
	}

	client := &http.Client{Timeout: settings.Timeout}
	notifier := watchdog.Telegram{Client: client, Token: settings.TelegramToken, ChatID: settings.TelegramChat}
	dog := watchdog.New(settings.Config, watchdog.HTTPChecker{Client: client}, notifier, time.Now, log.Printf)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	log.Printf("info: watchdog watching %d target(s) every %s", len(settings.Targets), settings.Interval)
	if settings.Announce {
		if err := notifier.Send(ctx, settings.Texts.Started(len(settings.Targets))); err != nil {
			log.Printf("warning: start message not sent: %v", err)
		}
	}

	ticker := time.NewTicker(settings.Interval)
	defer ticker.Stop()
	for {
		dog.Poll(ctx)
		select {
		case <-ctx.Done():
			log.Printf("info: watchdog stopping")
			return
		case <-ticker.C:
		}
	}
}
