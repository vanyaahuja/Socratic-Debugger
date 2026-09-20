from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session as DBSession

from database.db import get_db
from database.repositories import list_problems, get_problem
from schemas import ProblemPublic

router = APIRouter(prefix="/problems", tags=["problems"])


@router.get("", response_model=list[ProblemPublic])
def get_problems(db: DBSession = Depends(get_db)):
    return list_problems(db)


@router.get("/{problem_id}", response_model=ProblemPublic)
def get_problem_detail(problem_id: int, db: DBSession = Depends(get_db)):
    problem = get_problem(db, problem_id)
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found")
    return problem
