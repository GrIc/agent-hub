package com.example.controller;

import org.springframework.web.bind.annotation.*;
import org.springframework.http.ResponseEntity;

/**
 * REST controller for authentication endpoints.
 * This is a synthetic file for testing grounding.
 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final UserService userService;

    public AuthController(UserService userService) {
        this.userService = userService;
    }

    /**
     * Login endpoint.
     * @param request login request
     * @return authentication token
     */
    @PostMapping("/login")
    public ResponseEntity<String> login(@RequestBody LoginRequest request) {
        User user = userService.authenticate(request.getEmail(), request.getPassword());
        if (user != null) {
            return ResponseEntity.ok("token");
        }
        return ResponseEntity.status(401).body("Unauthorized");
    }

    /**
     * Register endpoint.
     * @param request registration request
     * @return created user
     */
    @PostMapping("/register")
    public User register(@RequestBody RegisterRequest request) {
        User user = new User(request.getEmail(), request.getUsername(), request.getPassword());
        return userService.createUser(user);
    }
}
