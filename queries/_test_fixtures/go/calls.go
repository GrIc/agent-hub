package example

import (
	"fmt"
	"os"
)

// externalCall demonstrates external calls.
func externalCall() {
	fmt.Println("hello")
	os.Getwd()
}

// CallerService demonstrates internal calls.
type CallerService struct{}

// DoWork calls validate and process.
func (c *CallerService) DoWork() {
	c.validate()
	c.process()
	externalCall()
}

// validate checks validity.
func (c *CallerService) validate() bool {
	return true
}

// process does the work.
func (c *CallerService) process() {
	c.validate()
}
