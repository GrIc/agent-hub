/**
 * TypeScript methods fixture for AST fixture testing.
 */

class Calculator {
    add(a: number, b: number): number {
        return a + b;
    }

    subtract(a: number, b: number): number {
        return a - b;
    }

    multiply(a: number, b: number): number {
        return a * b;
    }

    divide(a: number, b: number): number {
        if (b === 0) {
            throw new Error("Division by zero");
        }
        return a / b;
    }

    calculate(operation: string, a: number, b: number): number {
        const method = (this as any)[operation];
        return method.call(this, a, b);
    }
}
