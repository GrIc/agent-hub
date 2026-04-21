package com.example.repository;

import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

/**
 * Repository for User entities.
 * This is a synthetic file for testing grounding.
 */
public interface UserRepository extends JpaRepository<User, Long> {

    /**
     * Find user by email address.
     * @param email user email
     * @return optional user
     */
    Optional<User> findByEmail(String email);

    /**
     * Find user by username.
     * @param username user username
     * @return optional user
     */
    Optional<User> findByUsername(String username);
}
