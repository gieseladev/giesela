package main

import (
	"github.com/golang-migrate/migrate/v4"
	_ "github.com/golang-migrate/migrate/v4/database/postgres"
	_ "github.com/golang-migrate/migrate/v4/source/file"
)

func DoMigration() error {
	m, err := migrate.New(
		"file://configs/sql/migrate",
		"")
	if err != nil {
		return err
	}

	return m.Up()
}
