// Readability: Frontend module: keep browser state, API calls, and UI updates easy to follow.
/**
 * IndexedDB Manager for PPE CASM
 * Provides a simple Promise-based key-value store for local persistence.
 */
const IndexedDBManager = {
    DB_NAME: 'ppe_casm_db',
    STORE_NAME: 'cache',
    VERSION: 1,
    db: null,

    /**
     * Initialize the database
     */
    async init() {
        if (this.db) return this.db;

        // Return the prepared value to the caller.
        return new Promise((resolve, reject) => {
            const request = indexedDB.open(this.DB_NAME, this.VERSION);

            request.onupgradeneeded = (event) => {
                const db = event.target.result;
                // Choose the correct browser state branch before continuing.
                if (!db.objectStoreNames.contains(this.STORE_NAME)) {
                    db.createObjectStore(this.STORE_NAME);
                }
            };

            request.onsuccess = (event) => {
                this.db = event.target.result;
                resolve(this.db);
            };

            request.onerror = (event) => {
                console.error('[IndexedDB] Database error:', event.target.error);
                reject(event.target.error);
            };
        });
    },

    /**
     * Get a value by key
     */
    async getItem(key) {
        try {
            const db = await this.init();
            // Return the prepared value to the caller.
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([this.STORE_NAME], 'readonly');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.get(key);

                request.onsuccess = () => resolve(request.result);
                request.onerror = (event) => reject(event.target.error);
            });
        } catch (error) {
            console.warn('[IndexedDB] getItem failed:', error);
            // Return the prepared value to the caller.
            return null;
        }
    },

    /**
     * Set a value by key
     */
    async setItem(key, value) {
        try {
            const db = await this.init();
            // Return the prepared value to the caller.
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([this.STORE_NAME], 'readwrite');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.put(value, key);

                request.onsuccess = () => resolve(true);
                request.onerror = (event) => reject(event.target.error);
            });
        } catch (error) {
            console.warn('[IndexedDB] setItem failed:', error);
            // Return the prepared value to the caller.
            return false;
        }
    },

    /**
     * Remove an item by key
     */
    async removeItem(key) {
        try {
            const db = await this.init();
            // Return the prepared value to the caller.
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([this.STORE_NAME], 'readwrite');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.delete(key);

                request.onsuccess = () => resolve(true);
                request.onerror = (event) => reject(event.target.error);
            });
        } catch (error) {
            console.warn('[IndexedDB] removeItem failed:', error);
            // Return the prepared value to the caller.
            return false;
        }
    },

    /**
     * Clear the entire store
     */
    async clear() {
        try {
            const db = await this.init();
            // Return the prepared value to the caller.
            return new Promise((resolve, reject) => {
                const transaction = db.transaction([this.STORE_NAME], 'readwrite');
                const store = transaction.objectStore(this.STORE_NAME);
                const request = store.clear();

                request.onsuccess = () => resolve(true);
                request.onerror = (event) => reject(event.target.error);
            });
        } catch (error) {
            console.warn('[IndexedDB] clear failed:', error);
            // Return the prepared value to the caller.
            return false;
        }
    }
};
