import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import HTTPException, status, Depends
from fastapi.responses import JSONResponse  

from backend.models.user import User
from backend.models.transaction import Transaction
from backend.core.database import get_motor_client
from backend.core.config import logger 
from backend.schemas.wallet import ( 
    DepositWalletRequest,
    WithdrawWalletRequest
)
from backend.schemas.transaction import TransactionResponse 
from beanie.odm.fields import PydanticObjectId 
from backend.core.dependencies import get_current_user

class WalletService:
    @staticmethod
    async def get_wallet_data(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
        """
        **Эндпоинт для получения данных о кошельке пользователя.**
        Возвращает информацию о текущем кошельке пользователя.
        **Возвращает:**
        - `wallet`: Объект кошелька с его данными.
        """
        try:
            user = await User.get(current_user.id)
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            transactions = []
            if user.wallet.transactionIds:
                pipeline = [
                    {"$match": {"_id": {"$in": user.wallet.transactionIds}}},
                    {"$sort": {"date": -1}},
                    {"$limit": 50},
                    {"$project": {
                        "_id": {"$toString": "$_id"},
                        "userId": {"$toString": "$userId"},
                        "amount": 1,
                        "type": 1,
                        "status": 1,
                        "description": 1,
                        "paymentMethod": 1,
                        "currency": 1,
                        "date": {"$dateToString": {"format": "%Y-%m-%dT%H:%M:%S.%LZ", "date": "$date"}},
                        "createdAt": {"$dateToString": {"format": "%Y-%m-%dT%H:%M:%S.%LZ", "date": "$createdAt"}},
                        "updatedAt": {"$dateToString": {"format": "%Y-%m-%dT%H:%M:%S.%LZ", "date": "$updatedAt"}}
                    }}
                ]
                
                transactions_cursor = Transaction.aggregate(pipeline)
                transactions = await transactions_cursor.to_list(length=50)

            return {
                "success": True,
                "balance": user.wallet.balance,
                "transactions": transactions
            }

        except Exception as e:
            logger.error(f"Error getting wallet data: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail="Internal server error")

    @staticmethod
    async def deposit_wallet(request_data: DepositWalletRequest, current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
        """
        **Эндпоинт для пополнения кошелька пользователя.**
        Принимает данные о пополнении кошелька и текущем пользователе.
        **Параметры:**
        - `request_data`: Данные о пополнении (сумма и другие параметры).
        - `current_user`: Текущий пользователь.
        **Возвращает:**
        - `transaction`: Объект транзакции с ее данными.
        """
        try:
            client = get_motor_client()
        except RuntimeError as e:
            logger.error(f"Ошибка при пополнении кошелька: {e}. Клиент MongoDB не инициализирован.", exc_info=False)
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail='Ошибка сервера: База данных недоступна')

        async with await client.start_session() as session:
            async with session.start_transaction():
                try:
                    now_utc = datetime.now(timezone.utc)

                    transaction_data = Transaction(
                        userId=str(current_user.id), 
                        amount=request_data.amount,
                        type='deposit',
                        status='completed',
                        paymentMethod=request_data.paymentMethod,
                        description=f"Пополнение баланса на {request_data.amount} RUB",
                        date=now_utc,
                        createdAt=now_utc,
                        updatedAt=now_utc
                    )

                    inserted_transaction = await Transaction.insert_one(transaction_data, session=session)

                    await User.find_one(User.id == current_user.id).update(
                        {"$inc": {'wallet.balance': request_data.amount},
                        "$push": {'wallet.transactionIds': inserted_transaction.id}},
                        session=session
                    )

                    updated_user = await User.get(current_user.id, session=session)

                    await session.commit_transaction()

                    transaction_dict = inserted_transaction.model_dump(by_alias=True, mode='json')
                    transaction_dict['_id'] = str(transaction_dict['_id'])  
                    transaction_dict['userId'] = str(transaction_dict['userId'])  

                    final_response_payload = {
                        'success': True,
                        'newBalance': updated_user.wallet.balance,
                        'transaction': transaction_dict  
                    }
                    
                    logger.info(f"DEBUG: Final payload to be returned to FastAPI: {final_response_payload}")
                    return final_response_payload

                except Exception as err:
                    if session.in_transaction:
                        await session.abort_transaction()
                    logger.error(f'Ошибка при пополнении кошелька: {err}', exc_info=True)
                    if isinstance(err, HTTPException):
                        raise err
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))