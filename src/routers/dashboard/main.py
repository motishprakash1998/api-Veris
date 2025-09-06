from src.database.db import get_db
from sqlalchemy.orm import Session
from loguru import logger as logging
from src.utils.jwt import  get_email_from_token
from fastapi.security import OAuth2PasswordBearer
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
from fastapi import APIRouter, Depends, HTTPException
from src.routers.employees.models import employee as users_model
import json

# Defining the router
router = APIRouter(
    prefix="/api/dashboard",
    tags=["dashboard"],
    responses={404: {"description": "Not found"}},
)


@router.get("/get-user-qna/")
async def get_user_qna(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
):
    try:
        # Decode email from the token
        email = get_email_from_token(token)
        user = db.query(users_model.User).filter(users_model.User.email == email).first()

        if not user:
            raise HTTPException(status_code=404, detail="User not found.")

         # Fetch all QnA records for the user, sorted by id (question_id) in descending order
        qna_records = (
            db.query(qna_models.QnA)
            .filter(qna_models.QnA.user_id == user.id)
            .order_by(qna_models.QnA.id.desc())  # Replace `id` with `question_id` if applicable
            .all()
        )

        if not qna_records:
            return {
                "success": False,
                "status": 200,
                "message": "No QnA records found for the user.",
                "qna_list": []
            }

        # Format the data into a list of dictionaries
        qna_list = [
            {
                "qna_id": qna.id,
                "session_id": qna.session_id,
                "question_asked": qna.question_asked,
                "answer_given": qna.answer_given,
                "created_at": qna.created_at.isoformat() if qna.created_at else None,
                "updated_at": qna.updated_at.isoformat() if qna.updated_at else None
            }
            for qna in qna_records
        ]

        return {
            "success": True,
            "status": 200,
            "message": "QnA records retrieved successfully.",
            "qna_list": qna_list
        }
    except Exception as e:
        logging.error(f"Error in get_user_qna: {e}")
        raise HTTPException(status_code=500, detail="An error occurred while retrieving QnA records.")
    

# @router.get("/interview-report-analysis/")
# async def interview_report_analysis(
#     db: Session = Depends(get_db),
#     token: str = Depends(oauth2_scheme)
# ):
#     """
#     Provides an analysis of the user's interview performance, focusing on job title and job description.
#     """
#     try:
#         # Decode email from token
#         email = get_email_from_token(token)
#         user = db.query(users_model.User).filter(users_model.User.email == email).first()

#         if not user:
#             return {"success": False, "status": 404, "message": "User not found."}

#         # Fetch interview reports
#         reports = db.query(qna.InterviewReport).filter(qna.InterviewReport.user_email == user.email).all()

#         if not reports:
#             return {
#                 "success": True,
#                 "status": 200,
#                 "message": "No interview reports found for this user.",
#                 "analysis": {
#                     "Job Title": "N/A",
#                     "Job Description": "N/A",
#                     "Total Reports": 0,
#                     "Performance Overview": {},
#                     "Improvement Areas": []
#                 }
#             }

#         # Collect job title and description
#         job_title = reports[-1].job_title if reports[-1].job_title else "N/A"
#         job_description = reports[-1].job_description if reports[-1].job_description else "N/A"

#         # Calculate overall performance metrics
#         total_reports = len(reports)
#         total_questions = sum(report.total_questions for report in reports)
#         total_score = sum(report.total_score for report in reports)
#         max_possible_score = sum(report.max_possible_score for report in reports)
#         avg_score_percentage = (total_score / max_possible_score) * 100 if max_possible_score > 0 else 0

#         # Aggregate improvement areas
#         all_improvement_areas = []
#         for report in reports:
#             improvement_areas = report.areas_for_improvement
#             if improvement_areas:
#                 all_improvement_areas.extend(json.loads(improvement_areas))

#         # Identify top improvement areas
#         top_improvement_areas = {}
#         for area in all_improvement_areas:
#             question = area["question"]
#             top_improvement_areas[question] = top_improvement_areas.get(question, 0) + 1
#         top_areas_for_improvement = sorted(
#             top_improvement_areas.items(), key=lambda x: x[1], reverse=True
#         )[:5]

#         # Format performance overview
#         performance_overview = {
#             "Total Reports": total_reports,
#             "Total Questions": total_questions,
#             "Total Score": total_score,
#             "Maximum Possible Score": max_possible_score,
#             "Average Score Percentage": avg_score_percentage
#         }

#         return {
#             "success": True,
#             "status": 200,
#             "message": "Interview report analysis fetched successfully.",
#             "analysis": {
#                 "Job Title": job_title,
#                 "Job Description": job_description,
#                 "Performance Overview": performance_overview,
#                 "Improvement Areas": top_areas_for_improvement
#             }
#         }

#     except Exception as e:
#         logging.error(f"Error in interview_report_analysis: {e}")
#         return {"success": False, "status": 500, "message": "Internal server error."}
