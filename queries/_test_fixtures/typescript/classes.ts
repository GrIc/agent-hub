/**
 * TypeScript classes fixture for AST fixture testing.
 */

interface IAnimal {
    name: string;
    speak(): string;
}

class Animal implements IAnimal {
    constructor(public name: string) {}

    speak(): string {
        return `${this.name} makes a noise`;
    }
}

class Dog extends Animal {
    constructor(name: string, public breed: string) {
        super(name);
    }

    speak(): string {
        return `${this.name} barks`;
    }

    getBreed(): string {
        return this.breed;
    }
}

class Cat extends Animal {
    constructor(name: string) {
        super(name);
    }

    speak(): string {
        return `${this.name} meows`;
    }
}
