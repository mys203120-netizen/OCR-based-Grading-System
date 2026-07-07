from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_app_settings, get_instructor_id, get_message_sender
from app.api.submission_helpers import get_submission_for_instructor, message_response
from app.core.config import Settings
from app.core.database import get_session
from app.models import ClassRoom, Exam, SmsMessage, Student, Submission, utcnow
from app.schemas import GradingResult, MessageDraftCreate, MessageResponse
from app.services.json_utils import loads_model
from app.services.messaging import MessageSender, MessageSendError

router = APIRouter(tags=["messages"])


@router.post("/submissions/{submission_id}/messages/draft", response_model=MessageResponse)
async def create_message_draft(
    submission_id: str,
    payload: MessageDraftCreate,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_app_settings),
) -> MessageResponse:
    submission = await get_submission_for_instructor(session, submission_id, instructor_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="submission not found")
    if submission.student_id is None:
        raise HTTPException(status_code=400, detail="student must be assigned before messaging")
    student = await session.get(Student, submission.student_id)
    if student is None:
        raise HTTPException(status_code=404, detail="student not found")

    phone = student.parent_phone if payload.recipient == "parent" else student.student_phone
    if not phone:
        raise HTTPException(status_code=400, detail=f"{payload.recipient} phone is empty")
    graded = loads_model(submission.human_grade_json, GradingResult) or loads_model(
        submission.graded_json,
        GradingResult,
    )
    body = payload.body or (graded.parent_sms_draft if graded else None)
    if not body:
        body = f"{student.name} 학생의 서술형 채점 결과가 등록되었습니다."
    message = SmsMessage(
        submission_id=submission.id,
        phone=phone,
        body=body,
        status="draft",
        channel="kakao",
        provider=settings.message_provider,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    return message_response(message)


@router.post("/messages/{message_id}/send", response_model=MessageResponse)
async def send_message(
    message_id: str,
    instructor_id: str = Depends(get_instructor_id),
    session: AsyncSession = Depends(get_session),
    sender: MessageSender = Depends(get_message_sender),
) -> MessageResponse:
    result = await session.execute(
        select(SmsMessage)
        .join(Submission, Submission.id == SmsMessage.submission_id)
        .join(Exam, Exam.id == Submission.exam_id)
        .join(ClassRoom, ClassRoom.id == Exam.class_id)
        .where(SmsMessage.id == message_id)
        .where(ClassRoom.instructor_id == instructor_id)
    )
    message = result.scalar_one_or_none()
    if message is None:
        raise HTTPException(status_code=404, detail="message not found")
    if message.status in {"queued", "sent"}:
        return message_response(message)

    message.status = "queued"
    message.error_message = None
    await session.commit()
    try:
        send_result = await sender.send_kakao(phone=message.phone, body=message.body)
    except MessageSendError as exc:
        message.status = "failed"
        message.error_message = str(exc)
        await session.commit()
        await session.refresh(message)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    message.status = send_result.status
    message.provider_message_id = send_result.provider_message_id
    message.provider_payload_json = send_result.raw_response
    message.sent_at = utcnow()
    await session.commit()
    await session.refresh(message)
    return message_response(message)
