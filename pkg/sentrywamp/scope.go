package sentrywamp

import (
	"github.com/gammazero/nexus/v3/wamp"
	"github.com/getsentry/sentry-go"
	"strconv"
)

func id2string(id wamp.ID) string {
	return strconv.FormatUint(uint64(id), 10)
}

func ScopeAddSession(s *sentry.Scope, sess *wamp.Session) {
	if sess == nil {
		return
	}

	s.SetTag("session_id", id2string(sess.ID))
	s.SetExtra("session_details", sess.Details)
}

func ScopeAddMessage(s *sentry.Scope, msg wamp.Message) {
	if msg == nil {
		return
	}

	switch msg := msg.(type) {
	case *wamp.Invocation:
		s.SetTag("request_id", id2string(msg.Request))
		s.SetTag("registration_id", id2string(msg.Registration))
	case *wamp.Publish:
		s.SetTag("request_id", id2string(msg.Request))
		s.SetTag("topic", string(msg.Topic))
	}

	s.SetTag("message_type", strconv.Itoa(int(msg.MessageType())))
	s.SetExtra("msg", msg)
}
