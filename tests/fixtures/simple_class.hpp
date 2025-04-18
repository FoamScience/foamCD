/**
 * A simple class to test documentation parsing
 */
class SimpleClass {
public:
    /**
     * Constructor for SimpleClass
     * @param value Initial value
     */
    SimpleClass(int value);
    
    /**
     * Get the current value
     * @return Current value
     */
    int getValue() const;
    
    /**
     * Set a new value
     * @param value New value to set
     */
    void setValue(int value);
    
private:
    int m_value; ///< Internal value storage
};
