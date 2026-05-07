package example

// Calculator handles arithmetic.
type Calculator struct {
	Precision int
}

// Add returns a + b.
func (c *Calculator) Add(a int, b int) int {
	return a + b
}

// Subtract returns a - b.
func (c *Calculator) Subtract(a int, b int) int {
	return a - b
}

// Multiply returns a * b.
func (c *Calculator) Multiply(a int, b int) int {
	return a * b
}

// Divide returns a / b.
func (c *Calculator) Divide(a int, b int) (int, error) {
	if b == 0 {
		return 0, fmt.Errorf("division by zero")
	}
	return a / b, nil
}
