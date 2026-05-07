package com.example;

public class OuterClass {
    private String outerField;

    public class InnerClass {
        private String innerField;

        public String getInner() {
            return innerField;
        }
    }

    public InnerClass createInner() {
        return new InnerClass();
    }
}
