package com.example;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

@Service
public class AnnotatedService {

    @Autowired
    private String config;

    @Override
    public String toString() {
        return config;
    }
}
