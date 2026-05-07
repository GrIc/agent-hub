/**
 * TypeScript calls fixture for AST fixture testing.
 */

import * as path from 'path';
import { readFileSync } from 'fs';

function externalCall(): void {
    path.join('/tmp', 'file.txt');
    readFileSync('/tmp/file.txt');
    console.log("hello");
}

class CallerService {
    doWork(): void {
        this.validate();
        this.process();
        externalCall();
    }

    private validate(): boolean {
        return true;
    }

    private process(): void {
        this.validate();
    }
}

export { CallerService };
