package example

import "fmt"

// SimpleService is a simple Go struct.
type SimpleService struct {
	Name string
}

// GetName returns the name.
func (s *SimpleService) GetName() string {
	return s.Name
}

// SetName sets the name.
func (s *SimpleService) SetName(name string) {
	s.Name = name
}

// StandaloneFunction is a top-level function.
func StandaloneFunction(x int) int {
	return x * 2
}
