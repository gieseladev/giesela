package rbac

import (
	"errors"
	"strings"
	"unicode"
	"unicode/utf8"
)

// TargetType represents the type of entity a target targets.
type TargetType rune

const (
	UserTargetType    TargetType = 0   // Target user
	SpecialTargetType TargetType = '$' // Special target
	RoleTargetType    TargetType = '@' // Target role
)

// TODO special targets:
//	- guild_owner // guild only
//	- guild_admin // guild only
//	- everyone // guild / global

// GetTargetType determines the target type from its rune representation.
func GetTargetType(r rune) (TargetType, bool) {
	t := TargetType(r)
	switch t {
	case SpecialTargetType, RoleTargetType:
		return t, true
	default:
		return UserTargetType, unicode.IsDigit(r)

	}
}

const guildIDDelimiter = ":"

// Target is an identifier to which a role can be assigned.
//
// Syntax: `[<guild id>:][<type>]<id>`
//	As you can see both the guild id and the target type are optional.
//	A missing guild id indicates a global target and a missing type stands for
//	a user target type.
type Target struct {
	GuildID string
	Type    TargetType
	ID      string
}

func newTarget(guildID string, targetType TargetType, id string) Target {
	return Target{guildID, targetType, id}
}

func newTargetMust(guildID string, targetType TargetType, id string) Target {
	t := newTarget(guildID, targetType, id)
	if err := t.check(); err != nil {
		panic(err)
	}
	return t
}

func parseGuildTarget(target string) (Target, error) {
	firstRune, size := utf8.DecodeRuneInString(target)
	targetType, ok := GetTargetType(firstRune)
	if !ok {
		return Target{}, errors.New("invalid target type")
	}

	if targetType != UserTargetType {
		target = target[size:]
	}

	return newTarget("", targetType, target), nil
}

// ParseTarget parses a raw target into
func ParseTarget(raw string) (target Target, err error) {
	var guildTarget, guildID string

	parts := strings.SplitN(raw, guildIDDelimiter, 2)
	switch len(parts) {
	case 1:
		guildTarget = parts[0]
	case 2:
		guildTarget = parts[1]
		guildID = parts[0]
	}

	target, err = parseGuildTarget(guildTarget)
	if err != nil {
		return
	}

	target.GuildID = guildID

	return target, target.check()
}

// TargetUser creates a new target for a user.
func TargetUser(userID string) Target {
	return TargetMember("", userID)
}

// TargetMember creates a new target for a guild member.
func TargetMember(guildID string, userID string) Target {
	return newTargetMust(guildID, UserTargetType, userID)
}

// TargetRole creates a new target for a role.
func TargetRole(guildID string, roleID string) Target {
	return newTargetMust(guildID, RoleTargetType, roleID)
}

// check asserts that the target complies to the target type's contract.
func (t Target) check() error {
	if t.ID == "" {
		return errors.New("target must not be empty")
	}

	switch t.Type {
	case UserTargetType, SpecialTargetType:
		break // use explicit break to avoid confusion
	case RoleTargetType:
		if t.IsGlobal() {
			return errors.New("role targets must not be global")
		}
	default:
		return errors.New("invalid target type")
	}
	return nil
}

// GuildTarget returns the target without the guild specifier.
func (t Target) GuildTarget() string {
	if t.Type == UserTargetType {
		return t.ID
	}

	return string(t.Type) + t.ID
}

// String converts the target to its string representation.
func (t Target) String() string {
	if t.IsGlobal() {
		return t.GuildTarget()
	}

	return t.GuildID + guildIDDelimiter + t.GuildTarget()
}

// IsGlobal returns whether the target targets a global entity
// (i.e. is not bound to a guild).
func (t Target) IsGlobal() bool {
	return t.GuildID == ""
}

func (t Target) IsUser() bool {
	return t.IsGlobal() && t.Type == UserTargetType
}

func (t Target) IsMember() bool {
	return !t.IsGlobal() && t.Type == UserTargetType
}

func (t Target) IsRole() bool {
	return t.Type == RoleTargetType
}

func (t Target) IsSpecial() bool {
	return t.Type == SpecialTargetType
}
