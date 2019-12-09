package rbac

import (
	"github.com/go-redis/redis/v7"
	"strconv"
)

type Enforcer struct {
	redis     redis.UniversalClient
	keyPrefix string
}

func (e *Enforcer) targetHasPermission(target Target, permissions ...Permission) (bool, error) {
	keys := make([]string, len(permissions))
	for i, perm := range permissions {
		keys[i] = strconv.FormatInt(int64(perm), 10)
	}

	perms, err := e.redis.HMGet(e.keyPrefix+target.String(), keys...).Result()
	if err != nil {
		return false, err
	}

	for _, perm := range perms {
		if perm != nil {
			return true, nil
		}
	}

	return false, nil
}

// GetTargets generates all appropriate targets for a member or user.
func (e *Enforcer) GetTargets(guildID string, userID string) []Target {
	// TODO find roles, special targets
	return []Target{TargetMember(guildID, userID)}
}

// HasPermission checks whether a member or user has all of the permissions.
func (e *Enforcer) HasPermission(guildID string, userID string, permissions ...Permission) (bool, error) {
	if len(permissions) == 0 {
		return true, nil
	}

	targets := e.GetTargets(guildID, userID)

	for _, target := range targets {
		hasPerm, err := e.targetHasPermission(target, permissions...)
		if err != nil {
			return false, err
		}

		if hasPerm {
			return true, nil
		}
	}

	return false, nil
}
