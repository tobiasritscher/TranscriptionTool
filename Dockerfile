# Use an official Python runtime as a parent image
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1 # Prevents python from writing pyc files
ENV PYTHONUNBUFFERED 1     # Prevents python from buffering stdout/stderr

# Install system dependencies required by pydub (ffmpeg)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    # Clean up apt caches to reduce image size
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define environment variable for API key (user must provide this at runtime)
# ARG OPENAI_API_KEY
# ENV OPENAI_API_KEY=${OPENAI_API_KEY}
# Using ENV directly means the user *must* set it via `docker run -e` or similar
# It's better practice than ARG as ARG is only available during build.
ENV OPENAI_API_KEY="" 

# Ensure the uploads directory exists (though app.py creates it, this is belt-and-suspenders)
RUN mkdir -p /app/uploads

# Command to run the application using Flask's built-in server
# For production, consider using a more robust server like Gunicorn:
# CMD ["gunicorn", "--bind", "0.0.0.0:5000", "wsgi:app"]
# For simplicity here, we'll use the Flask development server (listening on all interfaces)
CMD ["flask", "run", "--host=0.0.0.0", "--port=5000"]

# If using gunicorn, you'd need a wsgi.py file:
# ```python
# # wsgi.py
# from app import app
#
# if __name__ == "__main__":
#     app.run()
# ```
# And add gunicorn to requirements.txt