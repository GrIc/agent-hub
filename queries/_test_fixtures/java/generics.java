package com.example;

import java.util.List;
import java.util.Map;

public class GenericRepository<T, V> {
    private Map<T, V> store;

    public V findById(T id) {
        return store.get(id);
    }

    public void save(T key, V value) {
        store.put(key, value);
    }

    public List<T> keys() {
        return null;
    }
}
