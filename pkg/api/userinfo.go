package api

import (
	"context"
	"fmt"
)

type UserInfo struct {
	UserID  string
	GuildID string
}

func (u UserInfo) String() string {
	if u.GuildID != "" {
		return fmt.Sprintf("%s:%s", u.GuildID, u.UserID)
	}

	return u.UserID
}

type userInfoKey struct{}

func WithUserInfo(ctx context.Context, user *UserInfo) context.Context {
	return context.WithValue(ctx, userInfoKey{}, user)
}

func UserInfoFromContext(ctx context.Context) (*UserInfo, bool) {
	user, ok := ctx.Value(userInfoKey{}).(*UserInfo)
	return user, ok
}

func UserInfoFromContextMust(ctx context.Context) *UserInfo {
	if user, ok := UserInfoFromContext(ctx); ok {
		return user
	}

	panic("expected user info value in context")
}
