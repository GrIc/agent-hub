package com.example.service;

import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

/**
 * User service handles user authentication and profile management.
 * This is a synthetic file for testing grounding.
 */
@Service
public class UserService {

    private final UserRepository userRepository;

    @Autowired
    public UserService(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    /**
     * Authenticate a user with email and password.
     * @param email user email
     * @param password user password
     * @return authenticated user or null
     */
    public User authenticate(String email, String password) {
        return userRepository.findByEmail(email)
                .filter(u -> u.getPasswordHash().equals(password))
                .orElse(null);
    }

    /**
     * Create a new user.
     * @param user user to create
     * @return created user
     */
    public User createUser(User user) {
        return userRepository.save(user);
    }

    /**
     * Get user by ID.
     * @param id user ID
     * @return user or empty
     */
    public java.util.Optional<User> getUserById(Long id) {
        return userRepository.findById(id);
    }
}
