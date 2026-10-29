from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views import generic
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User

from .models import Course, Enrollment, Question, Choice, Submission

import logging

logger = logging.getLogger(__name__)


def registration_request(request):
    context = {}

    if request.method == "GET":
        return render(
            request,
            "onlinecourse/user_registration_bootstrap.html",
            context,
        )

    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["psw"]
        first_name = request.POST["firstname"]
        last_name = request.POST["lastname"]

        if User.objects.filter(username=username).exists():
            context["message"] = "User already exists."
            return render(
                request,
                "onlinecourse/user_registration_bootstrap.html",
                context,
            )

        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            password=password,
        )
        login(request, user)
        return redirect("onlinecourse:index")


def login_request(request):
    context = {}

    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["psw"]
        user = authenticate(username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect("onlinecourse:index")

        context["message"] = "Invalid username or password."

    return render(
        request,
        "onlinecourse/user_login_bootstrap.html",
        context,
    )


def logout_request(request):
    logout(request)
    return redirect("onlinecourse:index")


def check_if_enrolled(user, course):
    if not user.is_authenticated:
        return False

    return Enrollment.objects.filter(
        user=user,
        course=course,
    ).exists()


class CourseListView(generic.ListView):
    template_name = "onlinecourse/course_list_bootstrap.html"
    context_object_name = "course_list"

    def get_queryset(self):
        user = self.request.user
        courses = Course.objects.order_by("-total_enrollment")[:10]

        for course in courses:
            course.is_enrolled = check_if_enrolled(user, course)

        return courses


class CourseDetailView(generic.DetailView):
    model = Course
    template_name = "onlinecourse/course_details_bootstrap.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        course = context["course"]
        course.is_enrolled = check_if_enrolled(
            self.request.user, course
        )
        return context


def enroll(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    user = request.user

    if user.is_authenticated and not check_if_enrolled(user, course):
        Enrollment.objects.create(
            user=user,
            course=course,
            mode="honor",
        )
        course.total_enrollment += 1
        course.save(update_fields=["total_enrollment"])

    return HttpResponseRedirect(
        reverse("onlinecourse:course_details", args=(course.id,))
    )


def extract_answers(request):
    submitted_answers = []

    for key in request.POST:
        if key.startswith("choice"):
            for value in request.POST.getlist(key):
                try:
                    submitted_answers.append(int(value))
                except (ValueError, TypeError):
                    continue

    return submitted_answers


def submit(request, course_id):
    if request.method != "POST":
        return redirect("onlinecourse:course_details", pk=course_id)

    if not request.user.is_authenticated:
        return redirect("onlinecourse:login")

    course = get_object_or_404(Course, pk=course_id)

    enrollment = Enrollment.objects.filter(
        user=request.user,
        course=course,
    ).first()

    if enrollment is None:
        return redirect("onlinecourse:enroll", course_id=course.id)

    submitted_ids = extract_answers(request)

    # Accept only choices that belong to questions in this course.
    valid_choices = Choice.objects.filter(
        question__course=course,
        id__in=submitted_ids,
    )

    submission = Submission.objects.create(enrollment=enrollment)
    submission.choices.set(valid_choices)

    return redirect(
        "onlinecourse:show_exam_result",
        course_id=course.id,
        submission_id=submission.id,
    )


def show_exam_result(request, course_id, submission_id):
    if not request.user.is_authenticated:
        return redirect("onlinecourse:login")

    course = get_object_or_404(Course, pk=course_id)

    submission = get_object_or_404(
        Submission,
        pk=submission_id,
        enrollment__user=request.user,
        enrollment__course=course,
    )

    selected_ids = list(
        submission.choices.values_list("id", flat=True)
    )

    questions = course.question_set.prefetch_related("choice_set")

    results = []
    earned_points = 0
    possible = 0

    for question in questions:
        possible += question.grade
        is_correct = question.is_get_score(selected_ids)

        if is_correct:
            earned_points += question.grade

        results.append(
            {
                "question": question,
                "choices": question.choice_set.all(),
                "is_correct": is_correct,
                "selected_ids": selected_ids,
            }
        )

    grade = round((earned_points / possible) * 100) if possible else 0

    context = {
        "course": course,
        "submission": submission,
        "results": results,
        "grade": grade,
        "earned_points": earned_points,
        "total_points": possible,
        "possible": possible,
        "selected_ids": selected_ids,
    }

    return render(
        request,
        "onlinecourse/exam_result_bootstrap.html",
        context,
    )