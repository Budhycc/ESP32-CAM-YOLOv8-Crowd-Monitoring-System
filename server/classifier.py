from config import ROOM_CAPACITY, SEPI_MAX_RATIO, SEDANG_MAX_RATIO

def classify_crowd(person_count: int, capacity: int = ROOM_CAPACITY) -> dict:
    """
    Classifies room crowd density based on detected person count and room capacity.
    
    Rules:
    - Ratio <= 30%       -> Sepi
    - 30% < Ratio <= 70% -> Sedang
    - Ratio > 70%        -> Ramai
    
    Returns a dictionary containing percentage and status label.
    """
    if capacity <= 0:
        capacity = 1  # Avoid division by zero
        
    percentage = (person_count / capacity) * 100.0
    ratio = person_count / capacity
    
    if ratio <= SEPI_MAX_RATIO:
        status = "Sepi"
    elif ratio <= SEDANG_MAX_RATIO:
        status = "Sedang"
    else:
        status = "Ramai"
        
    return {
        "jumlah_orang": person_count,
        "kapasitas": capacity,
        "persentase": round(percentage, 1),
        "status": status
    }
