# AirConFix.py is a program to fix Sophies air conditioning system.
# The instructions are specific to a heat-pump: GE Model: ARH15AACB;  Serial # TR103055R
# The program flow is as follows:
# A test will be provided then based on the test results, the program will suggest a fix.

import sys

def welcome():
    print("=" * 60)
    print("Sophie's Air Conditioning Diagnostic Tool")
    print("GE Model: ARH15AACB | Serial #: TR103055R")
    print("=" * 60)
    print()

def get_yes_no(prompt):
    while True:
        response = input(f"{prompt} (y/n): ").lower().strip()
        if response in ['y', 'yes']:
            return True
        elif response in ['n', 'no']:
            return False
        else:
            print("Please enter 'y' for yes or 'n' for no.")

def power_test():
    print("\n--- POWER TEST ---")
    if not get_yes_no("Is the unit plugged in?"):
        return "Check power cord connection. Ensure outlet has power."
    
    if not get_yes_no("Are any lights or displays on the unit working?"):
        return "Check circuit breaker. Test outlet with another device. May need electrician."
    
    if not get_yes_no("Does the unit respond to remote control or manual buttons?"):
        return "Replace remote batteries. Try manual controls on unit. Check for interference."
    
    return None

def cooling_test():
    print("\n--- COOLING TEST ---")
    if not get_yes_no("Is the unit set to cooling mode?"):
        return "Set unit to cooling mode and lower temperature setting."
    
    if not get_yes_no("Is air flowing from the unit?"):
        # Extended motor diagnostics when no air flow
        if get_yes_no("Can you hear the indoor fan motor running?"):
            return "Indoor fan running but no airflow. Check for blocked vents, damaged fan blades, or disconnected ductwork."
        else:
            if get_yes_no("Can you hear any clicking or humming sounds from the unit?"):
                return "Motor may be seized or capacitor failed. Turn off unit and contact technician - potential fire hazard."
            else:
                return "No motor sounds detected. Check fan motor connections, control board, or motor may need replacement."
    
    if not get_yes_no("Can you hear the outdoor compressor running?"):
        if get_yes_no("Is the outdoor fan running?"):
            return "Outdoor fan runs but compressor doesn't. Likely compressor failure or electrical issue. Contact technician."
        else:
            return "Neither outdoor fan nor compressor running. Check outdoor disconnect switch, capacitor, or contactor."
    
    if not get_yes_no("Is the air coming out cool?"):
        temp_diff = input("What's the temperature difference between intake and output? (enter number or 'unknown'): ")
        if temp_diff.lower() == 'unknown' or (temp_diff.isdigit() and int(temp_diff) < 10):
            return "Low refrigerant likely. Contact HVAC technician for refrigerant check/recharge."
    
    if not get_yes_no("Does the unit cool the room adequately?"):
        return "Unit may be undersized for room. Check for air leaks. Clean outdoor condenser coils."
    
    return None

def heating_test():
    print("\n--- HEATING TEST ---")
    if not get_yes_no("Is the unit set to heating mode?"):
        return "Set unit to heating mode and higher temperature setting."
    
    if not get_yes_no("Is warm air flowing from the unit?"):
        return "Check defrost cycle. Clean outdoor unit of ice/debris. May need professional service."
    
    if not get_yes_no("Does the unit heat the room adequately?"):
        return "Heat pumps lose efficiency in cold weather. Consider backup heating or service check."
    
    return None

def noise_test():
    print("\n--- NOISE TEST ---")
    if get_yes_no("Is the unit making unusual noises?"):
        noise_type = input("What type of noise? (grinding/squealing/clicking/rattling/other): ").lower()
        
        if "grinding" in noise_type or "squealing" in noise_type:
            return "Motor or fan bearing issue. Turn off unit and contact technician immediately."
        elif "clicking" in noise_type:
            return "Possible electrical relay issue. Monitor and contact technician if persists."
        elif "rattling" in noise_type:
            return "Check for loose panels or debris. Tighten screws and clean unit."
        else:
            return "Unusual noise detected. Contact technician for inspection."
    
    return None

def filter_maintenance():
    print("\n--- MAINTENANCE CHECK ---")
    if not get_yes_no("Has the air filter been cleaned/replaced in the last 3 months?"):
        return "Clean or replace air filter. Dirty filters reduce efficiency and can damage unit."
    
    if not get_yes_no("Has the outdoor unit been cleaned recently?"):
        return "Clean outdoor condenser coils with water. Remove debris around unit."
    
    return None

def run_diagnostics():
    welcome()
    
    issues = []
    
    # Run all tests
    tests = [
        ("Power", power_test),
        ("Cooling", cooling_test),
        ("Heating", heating_test),
        ("Noise", noise_test),
        ("Maintenance", filter_maintenance)
    ]
    
    for test_name, test_func in tests:
        result = test_func()
        if result:
            issues.append(f"{test_name}: {result}")
    
    # Display results
    print("\n" + "=" * 60)
    print("DIAGNOSTIC RESULTS")
    print("=" * 60)
    
    if not issues:
        print("✓ No issues detected. Unit appears to be functioning normally.")
        print("\nRecommended maintenance:")
        print("- Clean/replace air filter monthly")
        print("- Keep outdoor unit clear of debris")
        print("- Schedule annual professional maintenance")
    else:
        print("Issues found and recommended fixes:")
        print()
        for i, issue in enumerate(issues, 1):
            print(f"{i}. {issue}")
        
        print("\n⚠️  If problems persist after trying these fixes,")
        print("   contact a qualified HVAC technician.")
    
    print("\n" + "=" * 60)

def main():
    try:
        run_diagnostics()
    except KeyboardInterrupt:
        print("\n\nDiagnostic cancelled by user.")
        sys.exit(0)
    except Exception as e:
        print(f"\nAn error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()

