from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from supabase import create_async_client
from app.core.config import settings
from app.core.auth import get_current_user

router = APIRouter(prefix="/auth")


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register")
async def register(request: AuthRequest):
    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        response = await supabase.auth.sign_up(
            {"email": request.email, "password": request.password}
        )
        if not response or not response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration failed",
            )
        return {
            "message": "User registered successfully",
            "user_id": response.user.id,
            "email": response.user.email,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/login")
async def login(request: AuthRequest):
    try:
        supabase = await create_async_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        response = await supabase.auth.sign_in_with_password(
            {"email": request.email, "password": request.password}
        )
        if not response or not response.session:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password",
            )
        return {
            "access_token": response.session.access_token,
            "token_type": "bearer",
            "expires_in": response.session.expires_in,
            "user": {
                "id": response.user.id,
                "email": response.user.email,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )


@router.get("/me")
async def me(user=Depends(get_current_user)):
    return {
        "id": user.id,
        "email": user.email,
        "created_at": str(user.created_at),
    }
