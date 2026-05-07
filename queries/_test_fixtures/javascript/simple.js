/**
 * Simple JavaScript module for AST fixture testing.
 */

class SimpleService {
    constructor(name) {
        this.name = name;
    }

    getName() {
        return this.name;
    }

    setName(name) {
        this.name = name;
    }
}

function standaloneFunction(x) {
    return x * 2;
}

module.exports = { SimpleService, standaloneFunction };
