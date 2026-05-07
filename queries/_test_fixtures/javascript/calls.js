/**
 * JavaScript calls fixture for AST fixture testing.
 */

const path = require('path');
const fs = require('fs');

function externalCall() {
    path.join('/tmp', 'file.txt');
    fs.readFileSync('/tmp/file.txt');
    console.log("hello");
}

class CallerService {
    doWork() {
        this.validate();
        this.process();
        externalCall();
    }

    validate() {
        return true;
    }

    process() {
        this.validate();
    }
}
