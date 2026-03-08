.PHONY: build build-linux run debug test vet clean

# Build for the current OS (development)
build:
	go build -o bin/agent ./cmd/agent

# Cross-compile for Debian/Linux staging server
build-linux:
	GOOS=linux GOARCH=amd64 go build -o bin/agent-linux ./cmd/agent

# Run locally (requires Redis on localhost:6379)
run:
	go run ./cmd/agent

# Run in debug mode — prints metrics to stdout, no Redis needed
debug:
	MAESTRO_DEBUG=true go run ./cmd/agent

# Run on the staging Debian server (set STAGING_HOST before calling)
# Usage: make deploy STAGING_HOST=user@your-server-ip
deploy: build-linux
	scp bin/agent-linux $(STAGING_HOST):~/maestro-agent
	ssh $(STAGING_HOST) "chmod +x ~/maestro-agent && ~/maestro-agent"

test:
	go test ./...

vet:
	go vet ./...

clean:
	rm -f bin/agent bin/agent-linux
