package com.example;

import com.example.OtherService;

public class CallerService {
    private OtherService other;

    public void doWork() {
        other.process();
        this.validate();
        helper();
    }

    private void validate() {
        // validation logic
    }

    private void helper() {
        doWork();
    }
}
