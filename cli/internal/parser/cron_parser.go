package parser

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// ParseCron converts natural language to cron expression
func ParseCron(input string) (string, error) {
	input = strings.TrimSpace(strings.ToLower(input))
	
	// If it already looks like a cron expression, return as-is
	if isCronExpression(input) {
		return input, nil
	}
	
	// "every X minutes"
	if strings.HasPrefix(input, "every ") && strings.Contains(input, "minute") {
		return parseEveryMinutes(input)
	}
	
	// "every hour" or "hourly"
	if input == "every hour" || input == "hourly" {
		return "0 * * * *", nil
	}
	
	// "every day" or "daily"
	if input == "every day" || input == "daily" {
		return "0 9 * * *", nil // 9am daily
	}
	
	// "daily at HH:MM"
	if strings.HasPrefix(input, "daily at ") {
		return parseDailyAt(input)
	}
	
	// "every monday/tuesday/etc"
	if strings.HasPrefix(input, "every ") && containsWeekday(input) {
		return parseEveryWeekday(input)
	}
	
	// "every weekday"
	if input == "every weekday" || input == "weekdays" {
		return "0 9 * * 1-5", nil // 9am Mon-Fri
	}
	
	// "every weekend"
	if input == "every weekend" || input == "weekends" {
		return "0 9 * * 0,6", nil // 9am Sat-Sun
	}
	
	// "monthly"
	if input == "monthly" {
		return "0 9 1 * *", nil // 9am on 1st of month
	}
	
	// "weekly"
	if input == "weekly" {
		return "0 9 * * 1", nil // 9am every Monday
	}
	
	return "", fmt.Errorf("unable to parse cron: %s\n\nSupported formats:\n  - Cron: */5 * * * * (every 5 min)\n  - Minutes: every 5 minutes, every 30 minutes\n  - Hourly: every hour, hourly\n  - Daily: daily, daily at 9am, daily at 14:30\n  - Weekday: every monday, every friday at 3pm\n  - Weekdays: every weekday, weekdays (Mon-Fri at 9am)\n  - Weekly: weekly (every Monday at 9am)\n  - Monthly: monthly (1st of month at 9am)", input)
}

func parseEveryMinutes(input string) (string, error) {
	// "every 5 minutes", "every 30 minutes"
	re := regexp.MustCompile(`^every\s+(\d+)\s+minutes?$`)
	matches := re.FindStringSubmatch(input)
	
	if len(matches) != 2 {
		return "", fmt.Errorf("invalid format: %s (expected: every X minutes)", input)
	}
	
	minutes, _ := strconv.Atoi(matches[1])
	if minutes <= 0 || minutes > 59 {
		return "", fmt.Errorf("minutes must be between 1 and 59")
	}
	
	return fmt.Sprintf("*/%d * * * *", minutes), nil
}

func parseDailyAt(input string) (string, error) {
	// "daily at 9am", "daily at 14:30"
	timeStr := strings.TrimPrefix(input, "daily at ")
	timeStr = strings.TrimSpace(timeStr)
	
	hour, minute, err := parseTimeOfDay(timeStr)
	if err != nil {
		return "", err
	}
	
	return fmt.Sprintf("%d %d * * *", minute, hour), nil
}

func parseEveryWeekday(input string) (string, error) {
	// "every monday", "every friday at 3pm"
	re := regexp.MustCompile(`^every\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:\s+at\s+(.+))?$`)
	matches := re.FindStringSubmatch(input)
	
	if len(matches) < 2 {
		return "", fmt.Errorf("invalid format: %s", input)
	}
	
	dayName := matches[1]
	timeStr := ""
	if len(matches) > 2 {
		timeStr = matches[2]
	}
	
	// Get weekday number (0=Sunday, 1=Monday, etc.)
	weekdayNum := getWeekdayNumber(dayName)
	
	// Default to 9am if no time specified
	hour := 9
	minute := 0
	
	if timeStr != "" {
		var err error
		hour, minute, err = parseTimeOfDay(timeStr)
		if err != nil {
			return "", err
		}
	}
	
	return fmt.Sprintf("%d %d * * %d", minute, hour, weekdayNum), nil
}

func isCronExpression(input string) bool {
	// Basic check for cron pattern (5 fields separated by spaces)
	parts := strings.Fields(input)
	if len(parts) != 5 {
		return false
	}
	
	// Check if fields look cron-like
	cronPattern := regexp.MustCompile(`^[\d\*\-,/]+$`)
	for _, part := range parts {
		if !cronPattern.MatchString(part) {
			return false
		}
	}
	
	return true
}

func containsWeekday(input string) bool {
	weekdays := []string{"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
	for _, day := range weekdays {
		if strings.Contains(input, day) {
			return true
		}
	}
	return false
}

func getWeekdayNumber(day string) int {
	// Cron weekday numbers: 0=Sunday, 1=Monday, ..., 6=Saturday
	switch strings.ToLower(day) {
	case "sunday":
		return 0
	case "monday":
		return 1
	case "tuesday":
		return 2
	case "wednesday":
		return 3
	case "thursday":
		return 4
	case "friday":
		return 5
	case "saturday":
		return 6
	default:
		return 1
	}
}
