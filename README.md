# PersonaFlix v2.0 — Personalized Movie Recommendation System

PersonaFlix is a personalized movie recommendation web application built with Streamlit, FastAPI, Supabase, TMDB API, and TF-IDF-based recommendation logic.

## Live Demo

Frontend: Add your Streamlit Cloud link here  
Backend API: https://project-2-0-33xg.onrender.com/docs

## Features

- User registration and login
- JWT-based authentication
- Secure password hashing
- TMDB movie posters and details
- Movie rating system
- Duplicate-safe rating update
- My Ratings page
- Personalized For You recommendations
- Genre-based recommendation filtering
- For You pagination
- Deployed frontend and backend

## Tech Stack

- Python
- Streamlit
- FastAPI
- Supabase
- TMDB API
- scikit-learn
- TF-IDF
- Render
- Streamlit Cloud

## System Architecture

User → Streamlit Frontend → FastAPI Backend → Supabase Database  
FastAPI Backend → TMDB API  
FastAPI Backend → TF-IDF Recommendation Engine

## Recommendation Workflow

1. User rates movies.
2. Ratings are stored in Supabase.
3. Movies rated 4 or 5 are used as preference signals.
4. TF-IDF generates similar movie recommendations.
5. If TF-IDF cannot find a match, TMDB genre fallback is used.
6. Genre filters refine the final recommendations.
7. Results are shown in the For You section.

## Main API Endpoints

- POST `/register`
- POST `/login`
- POST `/rate`
- GET `/my-ratings`
- GET `/my-ratings/details`
- GET `/for-you`
- GET `/home`
- GET `/movie/id/{tmdb_id}`

## How to Run Locally

1. Clone the repository.
2. Create a virtual environment.
3. Install dependencies:

```bash
pip install -r requirements.txt
