FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt /app/

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . /app/

# List files for debugging
RUN ls -R /app

# Expose the port the app will run on
EXPOSE 8080

# Define the command to run the application
CMD ["python", "main.py"]