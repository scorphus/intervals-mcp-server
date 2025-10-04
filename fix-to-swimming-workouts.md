## Swimming Workout Generation Fixes for Intervals.icu Integration

These are directives for editing the Swimming Workout Generation Fixes for Intervals.icu Integration. The major issue is that the system requires a pace value for rest intervals, which is nonsensical. Swimmers cannot swim at "55% pace" for 15-30 seconds and magically return to the wall for the next interval. Additionally, the system does not account for the difference between pool and open water swimming, which can affect pacing and stroke rate.

### Problem 1: Rest Intervals Incorrectly Defined
**Current Issue**: Rest intervals between swimming sets are being defined with non-zero pace percentages (e.g., `"pace": {"units": "%pace", "value": 55}` for rest periods), which is nonsensical. Swimmers cannot swim at "55% pace" for 15-30 seconds and magically return to the wall for the next interval.

**Fix Required**: 
- For REST intervals (where swimmers stay at the wall), use `"pace": {"units": "%pace", "value": 0}` since the system requires a pace value
- Rest intervals should have both `"duration"` parameter in seconds AND `"pace": {"units": "%pace", "value": 0}`
- The text should clearly indicate "Rest" not any swimming action

**Example of correct rest interval**:
```json
{
  "duration": 15,
  "pace": {"units": "%pace", "value": 0},
  "text": "Rest"
}
```

### Problem 2: Warmup Structure Needs Better Organization
**Current Issue**: Drill sets and build sets are defined too simply

**Fix Required**: 
- When creating drill sets (e.g., 4x50 as 25 drill/25 swim), consider making them more explicit
- Build sets should clearly show progression (e.g., 4x25 build should specify 25@70%, 25@80%, 25@90%, 25@100%)

### Problem 3: Pool vs Open Water Considerations
**Current Issue**: Not distinguishing between pool-based and open water workouts clearly

**Fix Required**:
- Pool workouts: Use distance-based intervals with time-based REST at walls (pace = 0%)
- Open water workouts: Can use time-based "active recovery" (floating/treading) with very low pace values (e.g., 50-60%) since there are no walls
- Make this distinction clear in the workout structure

### Additional Notes:
- All steps MUST include a pace value due to system requirements
- For true rest periods at the wall, always use 0% pace
- For active recovery while swimming, use appropriate low pace percentages (55-65%)
- Total rest time should be calculated correctly (rest intervals with 0% pace shouldn't count toward moving_time)

### Summary for Implementation:
The main fix needed is using 0% pace for REST intervals at the wall. This is the standard workaround for devices that require a pace value even during rest periods. This affects how Wahoo/Garmin devices interpret the workout and ensures swimmers understand they should be resting at the wall, not swimming slowly.
