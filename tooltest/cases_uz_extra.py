"""
Extended Uzbek-focused tool-calling test set. Probes the weak spots found in
round 1 (edit_poll, quiz type) and adds variety: casual phrasing, mixed
Russian/Uzbek, rating scales, larger option lists, and tricky "don't
over-trigger" general questions that mention poll-ish words.
"""

CASES = [
    # ---- create_poll: varied phrasings ----
    dict(id="uzx_movie", lang="uz",
         msg="Yangi ovoz berish ochaylik: kino kechasi qaysi kun bo'lsin? Juma, Shanba, Yakshanba.",
         expect="create_poll", check=dict(n_options=3)),

    dict(id="uzx_pizza", lang="uz",
         msg="Hammaga savol bo'lsin: bugun pitsa buyurtma qilamizmi? Ha yoki Yo'q.",
         expect="create_poll", check=dict(n_options=2)),

    dict(id="uzx_rating", lang="uz",
         msg="1 dan 5 gacha baho so'rovnomasi yarat: tadbir qanday o'tdi? 1, 2, 3, 4, 5.",
         expect="create_poll", check=dict(n_options=5)),

    dict(id="uzx_anon_multi", lang="uz",
         msg="Anonim va bir nechta javob tanlasa bo'ladigan so'rovnoma yarat: qaysi tillarni bilasiz? o'zbek, rus, ingliz, turk.",
         expect="create_poll", check=dict(n_options=4, anonymous=True, multiple=True)),

    dict(id="uzx_quiz2", lang="uz",
         msg="Viktorina yarat: 2+2 nechiga teng? 3, 4, 5. To'g'ri javob 4.",
         expect="create_poll", check=dict(n_options=3, type="quiz", correct=1)),

    dict(id="uzx_mixed_ru", lang="uz",
         msg="Bittas opros qil: kofe yoki choy? Variantlar: Kofe, Choy.",
         expect="create_poll", check=dict(n_options=2)),

    dict(id="uzx_cities", lang="uz",
         msg="So'rovnoma yarat: qaysi shaharga sayohat qilamiz? Samarqand, Buxoro, Xiva, Nukus, Farg'ona.",
         expect="create_poll", check=dict(n_options=5, options_kw=["Xiva", "Nukus"])),

    # ---- edit_poll: the weak spot, more variety ----
    dict(id="uzx_edit_q", lang="uz",
         msg="So'rovnoma savolini o'zgartir, yangi savol: 'Eng yaxshi film qaysi?'",
         expect="edit_poll", check=dict(action="change_question")),

    dict(id="uzx_edit_remove", lang="uz",
         msg="So'rovnomadan 'banan' variantini olib tashla.",
         expect="edit_poll", check=dict(action="remove_option")),

    dict(id="uzx_edit_close", lang="uz",
         msg="Ovoz berishni to'xtat, so'rovnomani yop.",
         expect="edit_poll", check=dict(action="close")),

    dict(id="uzx_edit_add", lang="uz",
         msg="So'nggi so'rovnomaga 'Farqi yo'q' degan variantni qo'shib qo'y.",
         expect="edit_poll", check=dict(action="add_option")),

    # ---- general: should NOT trigger any tool (over-trigger trap) ----
    dict(id="uzx_gen_result", lang="uz",
         msg="Kechagi so'rovnoma natijalari qanday bo'ldi?",
         expect=None),

    dict(id="uzx_gen_opinion", lang="uz",
         msg="Sening fikringcha, so'rovnomalar foydalimi yoki yo'qmi?",
         expect=None),

    dict(id="uzx_gen_history", lang="uz",
         msg="Amir Temur qaysi yili tug'ilgan?",
         expect=None),

    dict(id="uzx_gen_math", lang="uz",
         msg="150 sonining 20 foizi qancha bo'ladi?",
         expect=None),
]
