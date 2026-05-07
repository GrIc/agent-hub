/**
 * Simple TypeScript module for AST fixture testing.
 */

class SimpleService {
    private name: string;

    constructor(name: string) {
        this.name = name;
    }

    getName(): string {
        return this.name;
    }

    setName(name: string): void {
        this.name = name;
    }
}

function standaloneFunction(x: number): number {
    return x * 2;
}

export { SimpleService, standaloneFunction };
