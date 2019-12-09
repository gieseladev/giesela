package main

import "fmt"

func main() {
	if err := DoMigration(); err != nil {
		fmt.Println(err)
	}
}
