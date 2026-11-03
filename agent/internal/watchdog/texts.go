package watchdog

import "fmt"

// Texts builds the messages the watchdog sends.
type Texts struct {
	down, stillDown, recovered, started string
}

var textsByLanguage = map[string]Texts{
	"pt-BR": {
		down:      "🔴 Vigia: %s não responde (%s)",
		stillDown: "🔴 Vigia: %s continua sem responder (%s)",
		recovered: "🟢 Vigia: %s voltou a responder",
		started:   "👁 Vigia ativo: acompanhando %d endereço(s)",
	},
	"en": {
		down:      "🔴 Watchdog: %s is not answering (%s)",
		stillDown: "🔴 Watchdog: %s is still not answering (%s)",
		recovered: "🟢 Watchdog: %s is answering again",
		started:   "👁 Watchdog running: watching %d address(es)",
	},
}

// TextsFor returns the texts of a language, Portuguese when it is unknown.
func TextsFor(language string) Texts {
	if texts, ok := textsByLanguage[language]; ok {
		return texts
	}
	return textsByLanguage["pt-BR"]
}

func (t Texts) Down(name, detail string) string      { return fmt.Sprintf(t.down, name, detail) }
func (t Texts) StillDown(name, detail string) string { return fmt.Sprintf(t.stillDown, name, detail) }
func (t Texts) Recovered(name string) string         { return fmt.Sprintf(t.recovered, name) }
func (t Texts) Started(count int) string             { return fmt.Sprintf(t.started, count) }
