package watchdog

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
)

const telegramAPI = "https://api.telegram.org"

// Telegram sends messages through the Bot API.
type Telegram struct {
	Client  *http.Client
	Token   string
	ChatID  string
	BaseURL string // empty means the public Bot API; tests point it elsewhere
}

type telegramReply struct {
	OK          bool   `json:"ok"`
	Description string `json:"description"`
}

func (t Telegram) Send(ctx context.Context, text string) error {
	base := t.BaseURL
	if base == "" {
		base = telegramAPI
	}
	payload, err := json.Marshal(map[string]any{
		"chat_id":                  t.ChatID,
		"text":                     text,
		"disable_web_page_preview": true,
	})
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, base+"/bot"+t.Token+"/sendMessage", bytes.NewReader(payload))
	if err != nil {
		return errors.New("telegram: invalid request")
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := t.Client.Do(req)
	if err != nil {
		// The error text carries the request URL, and the URL carries the token.
		return errors.New("telegram: " + strings.ReplaceAll(err.Error(), t.Token, "<token>"))
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, maxBodyBytes))
	if resp.StatusCode/100 == 2 {
		return nil
	}
	var reply telegramReply
	_ = json.Unmarshal(body, &reply)
	return fmt.Errorf("telegram: HTTP %d: %s", resp.StatusCode, reply.Description)
}
