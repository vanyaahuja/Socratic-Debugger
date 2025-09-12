import torch
from transformers import pipeline
import logging
import textwrap

# logging to suppress informational messages
logging.basicConfig(level=logging.WARNING)

model_id = "mistralai/Mistral-7B-Instruct-v0.3"
print(f"Loading model: {model_id}")

try:
    generator = pipeline(
        "text-generation",
        model=model_id,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    print("Model loaded successfully!")
except Exception as e:
    print(f"Error loading model: {e}")
    exit()

# A list of dictionaries, where each dictionary is one test case.
test_suite = [
    {
        "name": "Test Case 1: Logical Error (Incorrect Operator)",
        "code": """def get_large_numbers(numbers):
  # Should return numbers greater than 10
  large_numbers = []
  for num in numbers:
    if num < 10: # <-- The bug is here
      large_numbers.append(num)
  return large_numbers"""
    },
    {
        "name": "Test Case 2: Off-by-One Error (IndexError)",
        "code": """def double_values(numbers):
  # Double every number in the list
  for i in range(len(numbers) + 1): # <-- The bug is here
    numbers[i] = numbers[i] * 2
  return numbers"""
    },
    {
        "name": "Test Case 3: Mutation Error (Modifying List While Iterating)",
        "code": """def remove_odd_numbers(numbers):
  # Remove all odd numbers from the list
  for num in numbers:
    if num % 2 != 0:
      numbers.remove(num) # <-- The bug is here
  return numbers"""
    },
    {
        "name": "Test Case 4: Syntax Error (Missing Punctuation)",
        "code": """student_data = {
  "name": "Alex",
  "age": 20
  "major": "Computer Science" # <-- The bug is here
}"""
     },
    {
        "name": "Test Case 5: Correct Code (Control Case)",
        "code": """def calculate_area(length, width):
  # Calculates the area of a rectangle
  if length <= 0 or width <= 0:
    return 0
  return length * width"""
    }
]

# This loop will go through each test case, get the model's response, and print it.
for test_case in test_suite:
    print("\n" + "="*50)
    print(f"RUNNING: {test_case['name']}")
    print("="*50)


    prompt = f"""<s>[INST]
<<SYS>>
You are "Socrates," an expert Python programming tutor that uses the Socratic method.
- Your primary goal is to help the user discover the solution on their own.
- NEVER give the direct answer or solution.
- Ask ONE simple, open-ended question that focuses on the user's thinking process.
- Do not ask leading questions that hint at the answer
# Add this new rule to your prompt's <<SYS>> section:
- If the user's code is correct and has no bugs, respond by saying "This code looks correct. What would you like to do with it?".
<<SYS>>

A student has written the following Python code which contains a bug. Based on my instructions, ask a single Socratic question to help them.

Student's code:
```python
{textwrap.dedent(test_case['code'])}
[/INST]"""
    print("Generating response...")
    try:
      sequences = generator(
          prompt,
          do_sample=True,
          temperature=0.7,
          top_p=0.9,
          num_return_sequences=1,
          max_new_tokens=100,
          )

      response_text = sequences[0]['generated_text'].split('[/INST]')[-1].strip()
      print("\n--- Model's Response ---")
      print(response_text)
      print("--------------------------")
    except Exception as e:
      print(f"Error during text generation: {e}")
