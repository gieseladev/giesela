package rbac

import (
	"github.com/stretchr/testify/assert"
	"testing"
)

type Test struct {
	Name   string
	Input  string
	Target Target
	Error  bool
}

func (test *Test) Run(t *testing.T) {
	a := assert.New(t)

	target, err := ParseTarget(test.Input)
	if test.Error {
		a.Error(err)
		return
	}
	if !a.NoError(err) {
		return
	}

	a.Equal(test.Target, target)
}

func TestParseTarget(t *testing.T) {
	tests := []Test{
		// valid
		{"user", "68", Target{ID: "68", Type: UserTargetType}, false},
		{"member", "55:68", Target{GuildID: "55", ID: "68", Type: UserTargetType}, false},
		{"role", "55:@68", Target{GuildID: "55", ID: "68", Type: RoleTargetType}, false},
		{"special", "55:$owner", Target{GuildID: "55", ID: "owner", Type: SpecialTargetType}, false},
		// invalid
		{"role no guild", "@12", Target{}, true},
		{"invalid target type", "¬12", Target{}, true},
		{"empty", "", Target{}, true},
	}

	for _, test := range tests {
		t.Run(test.Name, test.Run)
	}
}
