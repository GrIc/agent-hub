package example

import "fmt"

// Animal is the base struct.
type Animal struct {
	Name string
}

// Speak returns a sound.
func (a *Animal) Speak() string {
	return fmt.Sprintf("%s makes a noise", a.Name)
}

// Dog extends Animal.
type Dog struct {
	Animal
	Breed string
}

// Speak returns a bark.
func (d *Dog) Speak() string {
	return fmt.Sprintf("%s barks", d.Name)
}

// Cat extends Animal.
type Cat struct {
	Animal
}

// Speak returns a meow.
func (c *Cat) Speak() string {
	return fmt.Sprintf("%s meows", c.Name)
}
