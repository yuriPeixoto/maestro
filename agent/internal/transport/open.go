package transport

import "log"

// Options selects and configures the backends behind the Sink.
type Options struct {
	ServerID string
	Mode     Mode
	// Debug prints every message to stdout and ignores Mode.
	Debug bool
	Redis RedisOptions
	NATS  NATSOptions
}

// Open connects the backends the mode asks for. A Redis that does not answer is fatal, as it always was;
// NATS is not, because its disk queue holds the data until the server is reachable.
func Open(opts Options) (*Router, error) {
	if opts.Debug {
		log.Printf("info [transport]: DEBUG mode — messages are printed to stdout")
		return newRouter(stdoutBackend{serverID: opts.ServerID}), nil
	}

	var backends []backend
	if opts.Mode.UsesRedis() {
		redisBackend, err := newRedisBackend(opts.ServerID, opts.Redis)
		if err != nil {
			return nil, err
		}
		backends = append(backends, redisBackend)
	}
	if opts.Mode.UsesNATS() {
		natsBackend, err := newNATSBackend(opts.ServerID, opts.NATS)
		if err != nil {
			newRouter(backends...).Close()
			return nil, err
		}
		backends = append(backends, natsBackend)
	}

	log.Printf("info [transport]: mode=%s", opts.Mode)
	return newRouter(backends...), nil
}
