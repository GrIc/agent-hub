/**
 * JavaScript classes fixture for AST fixture testing.
 */

class Animal {
    constructor(name) {
        this.name = name;
    }

    speak() {
        return `${this.name} makes a noise`;
    }
}

class Dog extends Animal {
    constructor(name, breed) {
        super(name);
        this.breed = breed;
    }

    speak() {
        return `${this.name} barks`;
    }

    getBreed() {
        return this.breed;
    }
}

class Cat extends Animal {
    constructor(name) {
        super(name);
    }

    speak() {
        return `${this.name} meows`;
    }
}
