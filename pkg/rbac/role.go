package rbac

import (
	"context"
	"database/sql"
	"errors"
	"github.com/gieseladev/giesela/pkg/models"
	"github.com/volatiletech/null"
	"github.com/volatiletech/sqlboiler/boil"
	"github.com/volatiletech/sqlboiler/queries"
	"github.com/volatiletech/sqlboiler/queries/qm"
)

type Role = models.Role
type RoleTarget = models.RoleTarget

func CreateRole(ctx context.Context, db *sql.DB, role *Role) error {
	switch {
	case role.Name == "":
		return errors.New("roles must have a name")
	case len(role.Permissions) == 0:
		return errors.New("roles must specify at least one permission")
	}

	return role.Insert(ctx, db, boil.Infer())
}

func GetRole(ctx context.Context, db *sql.DB, id int64) (*Role, error) {
	return models.FindRole(ctx, db, id)
}

func RoleByName(guildID string, name string) qm.QueryMod {
	var guildQM qm.QueryMod
	if guildID == "" {
		guildQM = models.RoleWhere.GuildID.IsNull()
	} else {
		guildQM = models.RoleWhere.GuildID.EQ(null.StringFrom(guildID))
	}

	nameQM := models.RoleWhere.Name.EQ(name)

	return qm.QueryModFunc(func(q *queries.Query) {
		qm.Apply(q,
			guildQM,
			nameQM,
		)
	})
}

func GetRoleByName(ctx context.Context, db *sql.DB, guildID string, name string) (*Role, error) {
	return models.Roles(RoleByName(guildID, name)).One(ctx, db)
}

func GetRoleTargetsForTarget(ctx context.Context, db *sql.DB, target string) ([]*RoleTarget, error) {
	return models.RoleTargets(
		models.RoleTargetWhere.Target.EQ(target),
		qm.Load(models.RoleTargetRels.Role),
	).All(ctx, db)
}
